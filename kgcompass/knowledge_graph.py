from neo4j import GraphDatabase
import os
from embedding import Embedding
from utils import relative_path
from config import (
    DECAY_FACTOR,
    VECTOR_SIMILARITY_WEIGHT,
)

DEFAULT_SOURCE_EXTENSIONS = (".py", ".cpp", ".java", ".h", ".hpp")
NONPROD_CONTEXT_DIRS = {
    "test",
    "tests",
    "__tests__",
    "test_suite",
    "docs",
    "doc",
    "examples",
    "example",
    "tutorial",
    "tutorials",
    "benchmarks",
    "benchmark",
}


def _source_extensions_for_directory_walk():
    raw_exts = os.getenv("KGCOMPASS_SOURCE_EXTENSIONS")
    if raw_exts:
        return tuple(ext.strip() for ext in raw_exts.split(",") if ext.strip())
    if os.getenv("FL_SCAN_CURRENT_LANG_ONLY", "0") == "1":
        return (".py",)
    return DEFAULT_SOURCE_EXTENSIONS


def _filter_walk_dirs(dirs):
    dirs[:] = [
        d for d in dirs
        if not d.startswith(".") and d not in {"__pycache__", "node_modules", "build", "dist"}
    ]
    if os.getenv("FL_SCAN_EXCLUDE_NONPROD_CONTEXT", "0") == "1":
        dirs[:] = [d for d in dirs if d.lower() not in NONPROD_CONTEXT_DIRS]


class KnowledgeGraph:
    def __init__(self, uri, user, password, database_name, init_embedder=True):
        database_name = database_name.replace('-', '').replace('_', '')
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.encountered_issues = set()
        self._similarity_graph_name = f"graph_{os.getpid()}_{database_name}"
        self._uniform_similarity_graph_name = f"graph_uniform_{os.getpid()}_{database_name}"
        self._similarity_projection_ready = False
        self._uniform_similarity_projection_ready = False
        self.embedder = None
        if init_embedder:
            try:
                self.embedder = Embedding()
                print("KnowledgeGraph: Embedding instance created successfully")
            except Exception as e:
                print(f"KnowledgeGraph: Embedding instance creation failed: {e}")
                raise

    def add_encountered_issue(self, issue_id):
        self.encountered_issues.add(issue_id)

    def close(self):
        # Best-effort cleanup for temporary GDS projection.
        try:
            self.drop_similarity_projection()
        except Exception:
            pass
        try:
            self.drop_similarity_projection(uniform_edge_weight=True)
        except Exception:
            pass
        self.driver.close()

    def _create_similarity_projection(self, session, graph_name=None, uniform_edge_weight=False):
        if uniform_edge_weight:
            graph_name = graph_name or self._uniform_similarity_graph_name
            node_query = (
                "MATCH (n) "
                "WHERE n:Issue OR n:Method OR n:Class OR n:File OR n:Directory "
                "OR n:Commit OR n:Experience OR n:Documentation "
                "RETURN id(n) AS id, labels(n) AS labels"
            )
            relationship_query = (
                "MATCH (s)-[:RELATED]->(t) "
                "RETURN id(s) AS source, id(t) AS target, 1.0 AS weight"
            )
            session.run(
                """
                CALL gds.graph.project.cypher(
                    $graph_name,
                    $node_query,
                    $relationship_query
                )
                """,
                graph_name=graph_name,
                node_query=node_query,
                relationship_query=relationship_query,
            )
            self._uniform_similarity_projection_ready = True
            return

        graph_name = graph_name or self._similarity_graph_name
        session.run("""
        CALL gds.graph.project(
            $graph_name,
            ['Issue', 'Method', 'Class', 'File', 'Directory', 'Commit', 'Experience', 'Documentation'],
            {
                RELATED: {
                    type: 'RELATED',
                    orientation: 'NATURAL',
                    properties: {
                        weight: {
                            property: 'weight',
                            defaultValue: 1.0
                        }
                    }
                }
            }
        )
        """, graph_name=graph_name)
        self._similarity_projection_ready = True

    def prepare_similarity_projection(self, graph_name=None, uniform_edge_weight=False):
        if graph_name is None:
            graph_name = (
                self._uniform_similarity_graph_name
                if uniform_edge_weight
                else self._similarity_graph_name
            )
        with self.driver.session() as session:
            # Keep behavior deterministic: always rebuild projection when preparing.
            session.run("CALL gds.graph.drop($graph_name, false)", graph_name=graph_name)
            self._create_similarity_projection(
                session,
                graph_name=graph_name,
                uniform_edge_weight=uniform_edge_weight,
            )

    def drop_similarity_projection(self, graph_name=None, uniform_edge_weight=False):
        if graph_name is None:
            graph_name = (
                self._uniform_similarity_graph_name
                if uniform_edge_weight
                else self._similarity_graph_name
            )
        with self.driver.session() as session:
            session.run("CALL gds.graph.drop($graph_name, false)", graph_name=graph_name)
        if uniform_edge_weight:
            self._uniform_similarity_projection_ready = False
        else:
            self._similarity_projection_ready = False

    def _get_embedding(self, text):
        if self.embedder is None:
            raise RuntimeError("Embedding is not initialized for this KnowledgeGraph instance.")
        return self.embedder.get_embedding(text[:4000])

    def create_method_entity(self, method_name, method_signature, file_path, start_line, end_line, source_code, doc_string='', weight=1):
        # First check if method already exists
        with self.driver.session() as session:
            exists_query = """
            MATCH (m:Method {name: $name, signature: $signature, file_path: $file_path})
            RETURN count(m) > 0 as exists
            """
            exists = session.run(exists_query,
                               name=method_name,
                               signature=method_signature,
                               file_path=file_path).single()['exists']

            if not exists:
                # If method doesn't exist, calculate embedding and create new method
                text_for_embedding = f"{method_name}\\n{doc_string or ''}\\n{source_code}"
                embedding = self._get_embedding(text_for_embedding)

                session.execute_write(self._create_and_link,
                                    method_name,
                                    method_signature,
                                    file_path,
                                    start_line,
                                    end_line,
                                    source_code,
                                    doc_string or '',  # Ensure doc_string is not None
                                    embedding,
                                    weight)
                # Create method-file relationship
                session.execute_write(self._link_method_to_file,
                                    method_name,
                                    method_signature,
                                    file_path,
                                    weight)

    @staticmethod
    def _create_and_link(tx, method_name, method_signature, file_path, start_line, end_line, source_code, doc_string, embedding, weight):
        # Truncate source_code if it's too large (Neo4j index limit is around 32KB)
        MAX_SOURCE_CODE_LENGTH = 20000  # Safe limit to avoid index issues
        truncated_source_code = source_code[:MAX_SOURCE_CODE_LENGTH] if len(source_code) > MAX_SOURCE_CODE_LENGTH else source_code

        # Debug info for large source code
        if len(source_code) > MAX_SOURCE_CODE_LENGTH:
            print(f"截断大源码: {method_name} ({len(source_code)} -> {len(truncated_source_code)} 字符)")

        # First, try to find if the method already exists
        find_query = """
        MATCH (m:Method {name: $method_name, signature: $method_signature, file_path: $file_path})
        RETURN m
        """
        existing_method = tx.run(find_query,
                               method_name=method_name,
                               method_signature=method_signature,
                               file_path=file_path).single()

        if existing_method:
            # Update existing method
            update_query = """
            MATCH (m:Method {name: $method_name, signature: $method_signature, file_path: $file_path})
            SET m.start_line = $start_line,
                m.end_line = $end_line,
                m.source_code = $source_code,
                m.doc_string = $doc_string,
                m.embedding = $embedding
            """
            tx.run(update_query,
                   method_name=method_name,
                   method_signature=method_signature,
                   file_path=file_path,
                   start_line=start_line,
                   end_line=end_line,
                   source_code=truncated_source_code,
                   doc_string=doc_string or '',
                   embedding=embedding)
        else:
            # Create new method - only index the key fields, then set large properties
            create_query = """
            CREATE (m:Method {
                name: $method_name,
                signature: $method_signature,
                file_path: $file_path,
                start_line: $start_line,
                end_line: $end_line
            })
            """
            tx.run(create_query,
                   method_name=method_name,
                   method_signature=method_signature,
                   file_path=file_path,
                   start_line=start_line,
                   end_line=end_line)

            # Set large properties separately to avoid index issues
            set_properties_query = """
            MATCH (m:Method {name: $method_name, signature: $method_signature, file_path: $file_path})
            SET m.source_code = $source_code,
                m.doc_string = $doc_string,
                m.embedding = $embedding
            """
            tx.run(set_properties_query,
                   method_name=method_name,
                   method_signature=method_signature,
                   file_path=file_path,
                   source_code=truncated_source_code,
                   doc_string=doc_string or '',
                   embedding=embedding)

    def clear_graph(self):
        with self.driver.session() as session:
            # Delete all nodes and relationships
            session.run("MATCH (n) DETACH DELETE n")

            try:
                # Delete all indexes
                for index in session.run("SHOW INDEXES"):
                    session.run(f"DROP INDEX {index['name']}")
            except Exception as e:
                print(f"Error deleting indexes: {e}")

            try:
                # Delete all constraints
                for constraint in session.run("SHOW CONSTRAINTS"):
                    session.run(f"DROP CONSTRAINT {constraint['name']}")
            except Exception as e:
                print(f"Error deleting constraints: {e}")

    def create_issue(self, issue_id, title, content=None):
        with self.driver.session() as session:
            # First check if issue already exists
            exists_query = """
            MATCH (i:Issue {id: $id})
            RETURN count(i) > 0 as exists
            """
            exists = session.run(exists_query, id=issue_id).single()['exists']

            if not exists:
                # If issue doesn't exist, calculate embedding and create new issue
                text_for_embedding = f"{title}\n{content}"
                embedding = self._get_embedding(text_for_embedding)
                session.execute_write(self._create_issue, issue_id, title, content, embedding)

    @staticmethod
    def _create_issue(tx, issue_id, title, content=None, embedding=None):
        query = (
            "MERGE (i:Issue {id: $issue_id}) "
            "SET i.title = $title, "
            "    i.content = $content, "
            "    i.name = $name, "
            "    i.embedding = $embedding "
        )
        tx.run(query, issue_id=issue_id, title=title, content=content, name=f"Issue:{issue_id}", embedding=embedding)

    def create_file_entity(self, file_path):
        """
        Create code file entity

        Args:
            file_path (str): File path
        """
        with self.driver.session() as session:
            session.execute_write(self._create_file, file_path)

    @staticmethod
    def _create_file(tx, file_path):
        query = (
            "MERGE (f:File {path: $file_path}) "
            "SET f.name = $name"
        )
        tx.run(query, file_path=file_path, name=relative_path(file_path))

    def create_directory_structure(self, base_path, code_analyzer, process_detail=False, weight=1):
        """
        Create directory structure, including directories and files and their relationships

        Args:
            base_path (str): Base path
        """
        with self.driver.session() as session:
            file_paths = session.execute_write(self._create_directory_structure, base_path)
            if process_detail and file_paths:
                for file_path in file_paths:
                    code_analyzer._build_file_class_methods(file_path)

    @staticmethod
    def _create_directory_structure(tx, base_path, weight=1):
        all_file_paths = []
        source_extensions = _source_extensions_for_directory_walk()
        for root, dirs, files in os.walk(base_path):
            _filter_walk_dirs(dirs)
            # Create current directory
            abs_dir_path = root.replace('\\', '/')
            rel_dir_path = relative_path(abs_dir_path)
            if os.path.basename(root).startswith('.'):
                continue
            # Create current directory node
            query = (
                "MERGE (d:Directory {path: $dir_path}) "
                "SET d.name = $name"
            )
            tx.run(query,
                dir_path=rel_dir_path or '/',
                name=os.path.basename(root) or '/'
            )
            # If not root directory, create relationship with parent directory
            if rel_dir_path:
                parent_dir_abs = os.path.dirname(abs_dir_path)
                parent_dir_path = relative_path(parent_dir_abs)
                query = (
                    "MATCH (parent:Directory {path: $parent_path}) "
                    "MATCH (child:Directory {path: $child_path}) "
                    "MERGE (parent)-[:RELATED {description: 'contains directory', weight: $weight}]->(child)"
                    "MERGE (child)-[:RELATED {description: 'contained in directory', weight: $weight}]->(parent)"
                )
                tx.run(query,
                    parent_path=parent_dir_path or '/',
                    child_path=rel_dir_path,
                    weight=weight
                )

            py_files = [f for f in files if f.endswith(source_extensions)]
            total_files = len(py_files)
            for idx, file in enumerate(py_files, 1):
                print(f'\nProcessing file [{idx}/{total_files}] ({(idx/total_files*100):.1f}%): {file}')
                file_abs_path = os.path.join(abs_dir_path, file)
                rel_file_path = relative_path(file_abs_path)

                # Create file node
                query = (
                    "MERGE (f:File {path: $file_path}) "
                    "SET f.name = $name"
                )
                tx.run(query,
                    file_path=rel_file_path,
                    name=rel_file_path
                )

                # Create directory-file relationship
                query = (
                    "MATCH (d:Directory {path: $dir_path}) "
                    "MATCH (f:File {path: $file_path}) "
                    "MERGE (d)-[:RELATED {description: 'contains file', weight: $weight}]->(f)"
                    "MERGE (f)-[:RELATED {description: 'contained in directory', weight: $weight}]->(d)"
                )
                all_file_paths.append(file_abs_path)
                tx.run(query,
                    dir_path=rel_dir_path or '/',
                    file_path=rel_file_path,
                    weight=weight
                )
        return all_file_paths

    def create_class_entity(self, class_name, file_path, start_line, end_line, source_code, doc_string="", weight=1):
        with self.driver.session() as session:
            # First check if class already exists
            exists_query = """
            MATCH (c:Class {name: $name, file_path: $file_path})
            RETURN count(c) > 0 as exists
            """
            exists = session.run(exists_query,
                               name=class_name,
                               file_path=file_path).single()['exists']

            if not exists:
                # If class doesn't exist, calculate embedding and create new class
                text_for_embedding = f"{class_name}\\n{doc_string or ''}\\n{source_code}"
                text_for_embedding = text_for_embedding[:8000]
                embedding = self._get_embedding(text_for_embedding)

                session.execute_write(self._create_class,
                                    class_name,
                                    file_path,
                                    start_line,
                                    end_line,
                                    source_code,
                                    doc_string or '',  # Ensure doc_string is not None
                                    embedding,
                                    weight)

    @staticmethod
    def _create_class(tx, class_name, file_path, start_line, end_line, source_code, doc_string="", embedding=None, weight=1):
        # Truncate source_code if it's too large (Neo4j index limit is around 32KB)
        MAX_SOURCE_CODE_LENGTH = 20000  # Safe limit to avoid index issues
        truncated_source_code = source_code[:MAX_SOURCE_CODE_LENGTH] if len(source_code) > MAX_SOURCE_CODE_LENGTH else source_code

        # Debug info for large source code
        if len(source_code) > MAX_SOURCE_CODE_LENGTH:
            print(f"截断大类源码: {class_name} ({len(source_code)} -> {len(truncated_source_code)} 字符)")

        # First, try to find if the class already exists
        find_query = """
        MATCH (c:Class {name: $class_name, file_path: $file_path})
        RETURN c
        """
        existing_class = tx.run(find_query,
                              class_name=class_name,
                              file_path=file_path).single()

        if existing_class:
            # Update existing class
            update_query = """
            MATCH (c:Class {name: $class_name, file_path: $file_path})
            SET c.start_line = $start_line,
                c.end_line = $end_line,
                c.source_code = $source_code,
                c.doc_string = $doc_string,
                c.embedding = $embedding,
                c.short_name = $short_name
            """
            tx.run(update_query,
                   class_name=class_name,
                   file_path=file_path,
                   start_line=start_line,
                   end_line=end_line,
                   source_code=truncated_source_code,
                   doc_string=doc_string or '',
                   embedding=embedding,
                   short_name=class_name.split('.')[-1])
        else:
            # Create new class - only index the key fields, then set large properties
            create_query = """
            CREATE (c:Class {
                name: $class_name,
                file_path: $file_path,
                start_line: $start_line,
                end_line: $end_line,
                short_name: $short_name
            })
            """
            tx.run(create_query,
                   class_name=class_name,
                   file_path=file_path,
                   start_line=start_line,
                   end_line=end_line,
                   short_name=class_name.split('.')[-1])

            # Set large properties separately to avoid index issues
            set_properties_query = """
            MATCH (c:Class {name: $class_name, file_path: $file_path})
            SET c.source_code = $source_code,
                c.doc_string = $doc_string,
                c.embedding = $embedding
            """
            tx.run(set_properties_query,
                   class_name=class_name,
                   file_path=file_path,
                   source_code=truncated_source_code,
                   doc_string=doc_string or '',
                   embedding=embedding)

        # Create relationship with file
        query = (
            "MATCH (f:File {path: $file_path}) "
            "MATCH (c:Class {name: $class_name, file_path: $file_path}) "
            "MERGE (f)-[:RELATED {description: 'contains class', weight: $weight}]->(c)"
            "MERGE (c)-[:RELATED {description: 'contained in file', weight: $weight}]->(f)"
        )
        tx.run(query, file_path=file_path, class_name=class_name, weight=weight)

    def link_class_to_method(self, class_name, file_path, method_name, method_signature, weight=1):
        """
        Establish association between class and method

        Args:
            class_name (str): Class name
            file_path (str): File path
            method_name (str): Method name
            method_signature (str): Method signature
        """
        with self.driver.session() as session:
            session.execute_write(self._link_class_to_method,
                                class_name, file_path, method_name, method_signature, weight)

    @staticmethod
    def _link_class_to_method(tx, class_name, file_path, method_name, method_signature, weight=1):
        query = (
            "MATCH (c:Class {name: $class_name, file_path: $file_path}) "
            "MATCH (m:Method {name: $method_name, signature: $method_signature, file_path: $file_path}) "
            "MERGE (c)-[:RELATED {description: 'contains method', weight: $weight}]->(m)"
            "MERGE (m)-[:RELATED {description: 'contained in class', weight: $weight}]->(c)"
        )
        tx.run(query,
            class_name=class_name,
            file_path=file_path,
            method_name=method_name,
            method_signature=method_signature,
            weight=weight
        )

    def link_issues(self, source_id, target_id, weight=1):
        """
        Establish relationship between two issues/PRs

        Args:
            source_id (str): Source issue/PR ID
            target_id (str): Target issue/PR ID
        """
        with self.driver.session() as session:
            query = """
            MATCH (source:Issue {id: $source_id})
            MATCH (target:Issue {id: $target_id})
            MERGE (source)-[:RELATED {description: 'points to issue', weight: $weight}]->(target)
            MERGE (target)-[:RELATED {description: 'referenced by issue', weight: $weight}]->(source)
            """
            session.run(query, {
                'source_id': source_id,
                'target_id': target_id,
                'weight': weight
            })

    def create_issue_entity_by_github_issue(self, issue):
        self.create_issue_entity(
            str(issue.number),
            getattr(issue, "kg_title", issue.title),
            issue.full_body or "",
            issue.created_at.timestamp(),
            issue.state,
            issue.pull_request is not None,
            f"{'pr' if issue.pull_request else 'issue'}#{issue.number}"
        )

    def create_issue_entity(self, issue_id, title, content, created_at, state, is_pr, name):
        """
        Create unified issue entity (including PRs)

        Args:
            issue_id (str): Issue/PR ID
            title (str): Title
            content (str): Content
            created_at (float): Creation timestamp
            state (str): State
            is_pr (bool): Whether it's a PR
            name (str): Entity name
        """
        with self.driver.session() as session:
            # First check if issue already exists
            exists_query = """
            MATCH (i:Issue {id: $id})
            RETURN count(i) > 0 as exists
            """
            exists = session.run(exists_query, id=issue_id).single()['exists']

            if not exists:
                # If issue doesn't exist, calculate embedding and create new issue
                text_for_embedding = f"{title}\n{content}"
                embedding = self._get_embedding(text_for_embedding)

                session.execute_write(self._create_issue_entity,
                                    issue_id, title, content,
                                    created_at, state, is_pr, name, embedding)

    @staticmethod
    def _create_issue_entity(tx, issue_id, title, content, created_at, state, is_pr, name, embedding):
        # Create or update entity
        query = """
        MERGE (i:Issue {id: $issue_id})
        ON CREATE SET
            i.title = $title,
            i.content = $content,
            i.created_at = $created_at,
            i.state = $state,
            i.is_pr = $is_pr,
            i.type = $type,
            i.name = $name,
            i.embedding = $embedding
        ON MATCH SET
            i.title = $title,
            i.content = $content,
            i.is_pr = $is_pr,
            i.type = $type,
            i.name = $name
        """
        tx.run(query,
               issue_id=issue_id,
               title=title,
               content=content,
               created_at=created_at,
               state=state,
               is_pr=is_pr,
               type='issue',
               name=name,
               embedding=embedding)

    def get_all_methods(self, top_k):
        """
        Get the 200 most relevant method entities for the given text

        Args:
            root_text (str): Base text for calculating similarity

        Returns:
            list: List of methods sorted by similarity
        """
        with self.driver.session() as session:
            query = """
            MATCH (root:Issue {id: 'root'})
            WHERE root.embedding IS NOT NULL
            WITH DISTINCT root, root.embedding as root_embedding,
                 root.title + ' ' + root.content as root_text

            MATCH (m:Method)
            WHERE m.embedding IS NOT NULL
            AND (NOT m.name CONTAINS 'test' OR m.name CONTAINS 'pytest')

            WITH m, root_embedding, root_text,
                 (gds.similarity.cosine(root_embedding, m.embedding) * $VECTOR_SIMILARITY_WEIGHT +
                  apoc.text.levenshteinSimilarity(root_text, m.source_code) * (1 - $VECTOR_SIMILARITY_WEIGHT)) as similarity
            ORDER BY similarity DESC
            LIMIT $top_k

            RETURN m.name as name,
                   m.file_path as file_path,
                   m.signature as signature,
                   m.source_code as source_code,
                   m.doc_string as doc_string,
                   m.title as title,
                   similarity
            """

            result = session.run(query, top_k=top_k, VECTOR_SIMILARITY_WEIGHT=VECTOR_SIMILARITY_WEIGHT)
            methods = [dict(record) for record in result]
            print(f"Found {len(methods)} related methods")
            return methods

    def link_issue_to_file(self, issue_id, file_path, weight=1):
        with self.driver.session() as session:
            session.execute_write(self._link_issue_to_file, issue_id, file_path, weight)

    def search_file_by_path(self, file_path):
        parts = file_path.replace('\\', '/').split('/')
        if '~' in parts:
            parts = parts[parts.index('~')+1:]
        if len(parts) > 3:
            parts = parts[-4:]
        target_filename = parts[-1]
        query = """
        MATCH (f:File)
        WITH f, $file_parts as parts, $target_filename as target
        WITH f, parts, target, f.path as path,
             last(split(f.path, '/')) as file_name,
             split(f.path, '/') as path_parts
        WITH f, parts, target, path, file_name, path_parts,
             [p in parts WHERE p IN path_parts] as matched_parts,
             CASE
                WHEN file_name = target THEN 3
                WHEN file_name STARTS WITH 'test_' THEN 0
                WHEN file_name CONTAINS replace(target, '_', '') THEN 1
                ELSE 0
             END as filename_match_score,
             apoc.coll.indexOf(path_parts, last(parts[..-1])) as dir_match
        WHERE size(matched_parts) >= 1
        WITH f, matched_parts, filename_match_score,
             CASE WHEN dir_match >= 0 THEN 2 ELSE 0 END as same_dir,
             reduce(s = 0, i IN range(0, size(matched_parts)-1) |
                s + CASE WHEN apoc.coll.indexOf(path_parts, matched_parts[i]) < apoc.coll.indexOf(path_parts, matched_parts[i+1])
                    THEN 1 ELSE 0 END
             ) as consecutive_count,
             size(matched_parts) as match_count
        RETURN {
            file: f,
            match_count: match_count,
            consecutive_count: consecutive_count,
            score: same_dir * 1000 + filename_match_score * 100 + match_count * 10 + consecutive_count
        } as result
        ORDER BY result.score DESC
        LIMIT 3
        """
        with self.driver.session() as session:
            results = session.run(query, file_parts=parts, target_filename=target_filename)
            matches = []
            for record in results:
                matches.append({
                    'file': record['result']['file'],
                    'score': record['result']['score']
                })
            return matches if matches else None

    @staticmethod
    def _link_issue_to_file(tx, issue_id, file_path, weight=1):
        query = (
            "MERGE (f:File {path: $file_path}) "
            "WITH f "
            "MATCH (i:Issue {id: $issue_id}) "
            "MERGE (i)-[:RELATED {description: 'points to file', weight: $weight}]->(f)"
            "MERGE (f)-[:RELATED {description: 'referenced by issue', weight: $weight}]->(i)"
        )
        tx.run(query,
               file_path=file_path,
               issue_id=issue_id,
               weight=weight)

    def create_commit_entity(self, commit_id, commit_message):
        query = """
        MERGE (c:Commit {id: $commit_id})
        SET c.message = $message
        """
        with self.driver.session() as session:
            session.run(query, commit_id=commit_id, message=commit_message)

    def link_issue_to_commit(self, issue_id, commit_id, weight=1):
        query = """
        MATCH (i:Issue {id: $issue_id})
        MATCH (c:Commit {id: $commit_id})
        MERGE (i)-[:RELATED {description: 'points to commit', weight: $weight}]->(c)
        MERGE (c)-[:RELATED {description: 'referenced by issue', weight: $weight}]->(i)
        """
        with self.driver.session() as session:
            session.run(query, issue_id=issue_id, commit_id=commit_id, weight=weight)

    def link_commit_to_file(self, commit_id, file_path, weight=1):
        query = """
        MERGE (f:File {path: $file_path})
        WITH f
        MATCH (c:Commit {id: $commit_id})
        MERGE (c)-[:RELATED {description: 'modified file', weight: $weight}]->(f)
        MERGE (f)-[:RELATED {description: 'modified by commit', weight: $weight}]->(c)
        """
        with self.driver.session() as session:
            session.run(query, commit_id=commit_id, file_path=file_path, weight=weight)

    def create_experience_entity(self, experience_id, title, content, source_type, created_at=None):
        query = """
        MERGE (e:Experience {id: $experience_id})
        SET e.title = $title,
            e.content = $content,
            e.source_type = $source_type,
            e.created_at = $created_at,
            e.name = $name
        """
        with self.driver.session() as session:
            session.run(
                query,
                experience_id=experience_id,
                title=title,
                content=content,
                source_type=source_type,
                created_at=created_at,
                name=f"Experience:{title}",
            )

    def link_issue_to_experience(self, issue_id, experience_id, weight=1):
        query = """
        MATCH (i:Issue {id: $issue_id})
        MATCH (e:Experience {id: $experience_id})
        MERGE (i)-[:RELATED {description: 'points to repair experience', weight: $weight}]->(e)
        MERGE (e)-[:RELATED {description: 'supports issue', weight: $weight}]->(i)
        """
        with self.driver.session() as session:
            session.run(query, issue_id=issue_id, experience_id=experience_id, weight=weight)

    def link_experience_to_file(self, experience_id, file_path, weight=1):
        query = """
        MERGE (f:File {path: $file_path})
        WITH f
        MATCH (e:Experience {id: $experience_id})
        MERGE (e)-[:RELATED {description: 'mentions file', weight: $weight}]->(f)
        MERGE (f)-[:RELATED {description: 'mentioned by repair experience', weight: $weight}]->(e)
        """
        with self.driver.session() as session:
            session.run(query, experience_id=experience_id, file_path=file_path, weight=weight)

    def create_documentation_entity(self, doc_id, title, content, path):
        query = """
        MERGE (d:Documentation {id: $doc_id})
        SET d.title = $title,
            d.content = $content,
            d.path = $path,
            d.name = $name
        """
        with self.driver.session() as session:
            session.run(
                query,
                doc_id=doc_id,
                title=title,
                content=content,
                path=path,
                name=f"Doc:{path}",
            )

    def link_issue_to_documentation(self, issue_id, doc_id, weight=1):
        query = """
        MATCH (i:Issue {id: $issue_id})
        MATCH (d:Documentation {id: $doc_id})
        MERGE (i)-[:RELATED {description: 'points to documentation', weight: $weight}]->(d)
        MERGE (d)-[:RELATED {description: 'supports issue', weight: $weight}]->(i)
        """
        with self.driver.session() as session:
            session.run(query, issue_id=issue_id, doc_id=doc_id, weight=weight)

    def link_documentation_to_file(self, doc_id, file_path, weight=1):
        query = """
        MERGE (f:File {path: $file_path})
        WITH f
        MATCH (d:Documentation {id: $doc_id})
        MERGE (d)-[:RELATED {description: 'mentions file', weight: $weight}]->(f)
        MERGE (f)-[:RELATED {description: 'mentioned by documentation', weight: $weight}]->(d)
        """
        with self.driver.session() as session:
            session.run(query, doc_id=doc_id, file_path=file_path, weight=weight)

    def link_method_to_commit(self, method_name, method_signature, file_path, commit_id, commit_message):
        query = """
        MATCH (m:Method {name: $method_name, signature: $signature, file_path: $file_path})
        MATCH (c:Commit {id: $commit_id})
        MERGE (m)-[r:RELATED {description: 'modified by commit', weight: 1}]->(c)
        MERGE (c)-[r2:RELATED {description: 'modified method', weight: 1}]->(m)
        SET r.message = $message
        """
        with self.driver.session() as session:
            session.run(
                query,
                method_name=method_name,
                signature=method_signature,
                file_path=file_path,
                commit_id=commit_id,
                message=commit_message
            )

    def link_method_to_issue(self, method_name, method_signature, file_path, issue_id, weight=1):
        with self.driver.session() as session:
            session.execute_write(self._link_method_to_issue,
                                method_name, method_signature, file_path, issue_id, weight)

    @staticmethod
    def _link_method_to_issue(tx, method_name, method_signature, file_path, issue_id, weight=1):
        query = (
            "MATCH (m:Method {name: $method_name, signature: $method_signature, file_path: $file_path}) "
            "MATCH (i:Issue {id: $issue_id}) "
            "MERGE (m)-[:RELATED {description: 'referenced by issue', weight: $weight}]->(i)"
            "MERGE (i)-[:RELATED {description: 'points to method', weight: $weight}]->(m)"
        )
        tx.run(query,
            method_name=method_name,
            method_signature=method_signature,
            file_path=file_path,
            issue_id=issue_id,
            weight=weight
        )

    def link_class_to_issue(self, class_name, file_path, issue_id, weight=1):
        with self.driver.session() as session:
            session.execute_write(self._link_class_to_issue,
                                class_name, file_path, issue_id, weight)

    @staticmethod
    def _link_class_to_issue(tx, class_name, file_path, issue_id, weight=1):
        query = (
            "MATCH (c:Class {name: $class_name, file_path: $file_path}) "
            "MATCH (i:Issue {id: $issue_id}) "
            "MERGE (c)-[:RELATED {description: 'referenced by issue', weight: $weight}]->(i)"
            "MERGE (i)-[:RELATED {description: 'points to class', weight: $weight}]->(c)"
        )
        tx.run(query,
            class_name=class_name,
            file_path=file_path,
            issue_id=issue_id,
            weight=weight
        )

    @staticmethod
    def _link_method_to_file(tx, method_name, method_signature, file_path, weight=1):
        query = (
            "MATCH (m:Method {name: $method_name, signature: $method_signature, file_path: $file_path}) "
            "MATCH (f:File {path: $file_path}) "
            "MERGE (f)-[:RELATED {description: 'contains method', weight: $weight}]->(m)"
            "MERGE (m)-[:RELATED {description: 'contained in file', weight: $weight}]->(f)"
        )
        tx.run(query,
            method_name=method_name,
            method_signature=method_signature,
            file_path=file_path,
            weight=weight
        )

    def link_method_calls(self, caller_name, caller_signature,
                         callee_name, callee_signature):
        with self.driver.session() as session:
            session.execute_write(self._link_method_calls,
                                caller_name, caller_signature,
                                callee_name, callee_signature)

    @staticmethod
    def _link_method_calls(tx, caller_name, caller_signature,
                          callee_name, callee_signature):
        query = (
            "MATCH (caller:Method {name: $caller_name, signature: $caller_signature}) "
            "MATCH (callee:Method {name: $callee_name, signature: $callee_signature}) "
            "MERGE (caller)-[r:RELATED {description: 'calls method', weight: 1}]->(callee) "
            "MERGE (callee)-[r2:RELATED {description: 'called by method', weight: 1}]->(caller)"
            "RETURN caller.name as caller, callee.name as callee"
        )
        result = tx.run(query,
            caller_name=caller_name,
            caller_signature=caller_signature,
            callee_name=callee_name,
            callee_signature=callee_signature,
        )


        record = result.single()
        if record:
            print(f"Created call relationship: {record['caller']} -> {record['callee']}")

    def get_method_by_name(self, method_name):
        with self.driver.session() as session:
            query = """
            MATCH (m:Method)
            WHERE m.name = $method_name
            RETURN m.name as name,
                    m.signature as signature,
                    m.file_path as file_path,
                    m.start_line as start_line,
                    m.end_line as end_line,
                    m.source_code as source_code,
                    m.doc_string as doc_string
            """
            result = session.run(query, method_name=method_name)
            return [{
                'name': record['name'],
                'signature': record['signature'],
                'file_path': record['file_path'],
                'start_line': record['start_line'],
                'end_line': record['end_line'],
                'source_code': record['source_code'],
                'doc_string': record['doc_string']
            } for record in result]

    def get_all_similarities_to_root(
        self,
        max_hops=2,
        limit=None,
        sort=False,
        decay_factor=None,
        vector_similarity_weight=None,
        reuse_projection=False,
        uniform_edge_weight=False,
    ):
        limit = limit or 500
        max_target_nodes = min(1000, limit * 2)
        decay_factor = DECAY_FACTOR if decay_factor is None else decay_factor
        vector_similarity_weight = (
            VECTOR_SIMILARITY_WEIGHT
            if vector_similarity_weight is None
            else vector_similarity_weight
        )
        identifier_boost_weight = float(os.getenv("KGCOMPASS_IDENTIFIER_BOOST_WEIGHT", "0"))
        evidence_path_boost_weight = float(os.getenv("KGCOMPASS_EVIDENCE_PATH_BOOST_WEIGHT", "0"))
        unsup_gnn_mode = os.getenv("KGCOMPASS_UNSUP_GNN_MODE", "off").lower()
        unsup_gnn_weight = float(os.getenv("KGCOMPASS_UNSUP_GNN_WEIGHT", "0.18"))
        unsup_gnn_alpha = float(os.getenv("KGCOMPASS_UNSUP_GNN_ALPHA", "0.85"))
        unsup_gnn_iterations = max(1, int(os.getenv("KGCOMPASS_UNSUP_GNN_ITERATIONS", "24")))
        graph_name = (
            self._uniform_similarity_graph_name
            if uniform_edge_weight
            else self._similarity_graph_name
        )
        projection_ready = (
            self._uniform_similarity_projection_ready
            if uniform_edge_weight
            else self._similarity_projection_ready
        )

        with self.driver.session() as session:
            try:
                if reuse_projection:
                    if not projection_ready:
                        session.run(
                            "CALL gds.graph.drop($graph_name, false)",
                            graph_name=graph_name,
                        )
                        self._create_similarity_projection(
                            session,
                            graph_name=graph_name,
                            uniform_edge_weight=uniform_edge_weight,
                        )
                else:
                    session.run(
                        "CALL gds.graph.drop($graph_name, false)",
                        graph_name=graph_name,
                    )
                    self._create_similarity_projection(
                        session,
                        graph_name=graph_name,
                        uniform_edge_weight=uniform_edge_weight,
                    )

                requested_concurrency = int(os.getenv("KG_GDS_CONCURRENCY", str(os.cpu_count() or 4)))
                # Unlicensed GDS is capped at concurrency=4.
                gds_concurrency = max(1, min(requested_concurrency, 4))
                if requested_concurrency != gds_concurrency:
                    print(
                        f"KG_GDS_CONCURRENCY={requested_concurrency} capped to {gds_concurrency} for unlicensed GDS."
                    )

                method_query = """
                MATCH (root:Issue {id: 'root'})
                WHERE root.embedding IS NOT NULL
                WITH root, root.embedding as root_embedding,
                    root.title + ' ' + root.content as root_text

                CALL gds.allShortestPaths.dijkstra.stream($graph_name, {
                    sourceNode: root,
                    relationshipWeightProperty: 'weight',
                    concurrency: $gds_concurrency
                })
                YIELD targetNode, nodeIds, totalCost

                WITH nodeIds, totalCost, root_embedding, root_text,
                    gds.util.asNode(targetNode) as m
                WHERE (m:Method OR m:Class AND NOT EXISTS((m)-[:RELATED]->(:Method)) OR m:Issue)
                  AND totalCost <= $max_hops
                  AND (m:Issue AND m.id <> 'root' OR NOT m:Issue)
                  AND m.embedding IS NOT NULL
                  AND (NOT m:Method OR NOT m.name CONTAINS 'test' OR m.name CONTAINS 'pytest')

                WITH m, nodeIds, totalCost, root_embedding, root_text,
                    [i IN range(0, size(nodeIds)-2) |
                        [
                            (start)-[rel:RELATED]-(end)
                            WHERE id(start) = nodeIds[i] AND id(end) = nodeIds[i+1] |
                            {
                                start_node: CASE
                                    WHEN start:Commit THEN 'Commit#' + start.id
                                    WHEN start:Experience THEN start.name
                                    WHEN start:Documentation THEN start.name
                                    WHEN start:Issue THEN start.name
                                    ELSE start.name
                                END,
                                end_node: CASE
                                    WHEN end:Commit THEN 'Commit#' + end.id
                                    WHEN end:Experience THEN end.name
                                    WHEN end:Documentation THEN end.name
                                    WHEN end:Issue THEN end.name
                                    ELSE end.name
                                END,
                                start_labels: labels(start),
                                end_labels: labels(end),
                                start_type: CASE
                                    WHEN start:Method THEN 'method'
                                    WHEN start:Class THEN 'class'
                                    WHEN start:File THEN 'file'
                                    WHEN start:Issue THEN 'issue'
                                    WHEN start:Commit THEN 'commit'
                                    WHEN start:Experience THEN 'experience'
                                    WHEN start:Documentation THEN 'documentation'
                                    WHEN start:Directory THEN 'directory'
                                    ELSE 'unknown'
                                END,
                                end_type: CASE
                                    WHEN end:Method THEN 'method'
                                    WHEN end:Class THEN 'class'
                                    WHEN end:File THEN 'file'
                                    WHEN end:Issue THEN 'issue'
                                    WHEN end:Commit THEN 'commit'
                                    WHEN end:Experience THEN 'experience'
                                    WHEN end:Documentation THEN 'documentation'
                                    WHEN end:Directory THEN 'directory'
                                    ELSE 'unknown'
                                END,
                                type: type(rel),
                                description: CASE
                                    WHEN id(start) = id(startNode(rel)) THEN rel.description
                                    ELSE CASE
                                        WHEN rel.description = 'contains method' THEN 'contained in method'
                                        WHEN rel.description = 'contained in method' THEN 'contains method'
                                        WHEN rel.description = 'contains class' THEN 'contained in class'
                                        WHEN rel.description = 'contained in class' THEN 'contains class'
                                        WHEN rel.description = 'contains file' THEN 'contained in file'
                                        WHEN rel.description = 'contained in file' THEN 'contains file'
                                        WHEN rel.description = 'points to issue' THEN 'referenced by issue'
                                        WHEN rel.description = 'referenced by issue' THEN 'points to issue'
                                        WHEN rel.description = 'calls method' THEN 'called by method'
                                        WHEN rel.description = 'called by method' THEN 'calls method'
                                        ELSE rel.description
                                    END
                                END
                            }
                        ][0]
                    ] as path_details

                WITH m, nodeIds, path_details, totalCost as cost, root_embedding, root_text,
                    CASE
                        WHEN m:Issue THEN
                            gds.similarity.cosine(root_embedding, m.embedding) * ($DECAY_FACTOR ^ totalCost)
                        ELSE
                            (gds.similarity.cosine(root_embedding, m.embedding) * $VECTOR_SIMILARITY_WEIGHT +
                            apoc.text.levenshteinSimilarity(root_text, m.source_code) * (1 - $VECTOR_SIMILARITY_WEIGHT)) *
                            ($DECAY_FACTOR ^ totalCost)
                    END as base_similarity
                WITH m, nodeIds, path_details, cost, base_similarity, root_text,
                    CASE
                        WHEN NOT m:Issue AND $IDENTIFIER_BOOST_WEIGHT > 0 THEN
                            CASE
                                WHEN m.name IS NOT NULL AND size(m.name) > 3
                                     AND toLower(root_text) CONTAINS toLower(m.name)
                                THEN $IDENTIFIER_BOOST_WEIGHT
                                ELSE 0
                            END
                            +
                            CASE
                                WHEN m.file_path IS NOT NULL
                                     AND toLower(root_text) CONTAINS toLower(last(split(m.file_path, '/')))
                                THEN $IDENTIFIER_BOOST_WEIGHT / 2.0
                                ELSE 0
                            END
                        ELSE 0
                    END as identifier_boost,
                    CASE
                        WHEN $EVIDENCE_PATH_BOOST_WEIGHT > 0
                             AND any(p IN path_details WHERE
                                 p.start_type IN ['commit', 'experience', 'documentation']
                                 OR p.end_type IN ['commit', 'experience', 'documentation'])
                        THEN $EVIDENCE_PATH_BOOST_WEIGHT
                        ELSE 0
                    END as evidence_path_boost
                WITH m, nodeIds, path_details, cost, base_similarity + identifier_boost + evidence_path_boost as similarity_score
                ORDER BY similarity_score DESC
                LIMIT 10000

                RETURN collect({
                    type: CASE
                        WHEN m:Method THEN 'method'
                        WHEN m:Class THEN 'class'
                        ELSE 'issue'
                    END,
                    name: m.name,
                    signature: CASE WHEN m:Method THEN m.signature ELSE null END,
                    file_path: CASE WHEN m:Method OR m:Class THEN m.file_path ELSE null END,
                    documentation: CASE WHEN m:Method OR m:Class THEN m.doc_string ELSE null END,
                    source_code: CASE WHEN m:Method OR m:Class THEN m.source_code ELSE null END,
                    start_line: CASE WHEN m:Method OR m:Class THEN m.start_line ELSE null END,
                    end_line: CASE WHEN m:Method OR m:Class THEN m.end_line ELSE null END,
                    issue_id: CASE WHEN m:Issue THEN m.id ELSE null END,
                    title: CASE WHEN m:Issue THEN m.title ELSE null END,
                    content: CASE WHEN m:Issue THEN m.content ELSE null END,
                    similarity: similarity_score,
                    distance: cost,
                    graph_node_id: id(m),
                    graph_node_ids: nodeIds,
                    path: path_details
                }) as methods
                """

                method_result = session.run(
                    method_query,
                    max_hops=float(max_hops),
                    max_target_nodes=max_target_nodes,
                    graph_name=graph_name,
                    gds_concurrency=gds_concurrency,
                    VECTOR_SIMILARITY_WEIGHT=vector_similarity_weight,
                    DECAY_FACTOR=decay_factor,
                    IDENTIFIER_BOOST_WEIGHT=identifier_boost_weight,
                    EVIDENCE_PATH_BOOST_WEIGHT=evidence_path_boost_weight,
                )
                method_record = method_result.single()
                method_similarities = method_record['methods'] if method_record else []
                if unsup_gnn_mode in {"pagerank", "unsup", "gnn"} and method_similarities:
                    graph_scores = self._compute_unsupervised_graph_rank_scores(
                        method_similarities,
                        alpha=unsup_gnn_alpha,
                        iterations=unsup_gnn_iterations,
                    )
                    if graph_scores:
                        for item in method_similarities:
                            candidate_node_id = item.get("graph_node_id")
                            graph_score = graph_scores.get(candidate_node_id, 0.0)
                            item["graph_score"] = graph_score
                            if unsup_gnn_weight > 0:
                                item["similarity"] = item["similarity"] + unsup_gnn_weight * graph_score

                results = {
                    'methods': list({
                        (sim['name'], sim.get('signature'), sim.get('file_path')): sim
                        for sim in method_similarities
                        if sim['type'] == 'method' and sim['similarity'] is not None
                    }.values()),
                    'classes': list({
                        (sim['name'], sim.get('file_path')): sim
                        for sim in method_similarities
                        if sim['type'] == 'class' and sim['similarity'] is not None
                    }.values()),
                    'issues': list({
                        sim['issue_id']: sim
                        for sim in method_similarities
                        if sim['type'] == 'issue' and sim['similarity'] is not None
                    }.values())
                }

                root_query = """
                MATCH (root:Issue {id: 'root'})
                RETURN {
                    type: 'issue',
                    name: root.name,
                    issue_id: root.id,
                    title: root.title,
                    content: root.content,
                    similarity: 2.0,
                    distance: 0,
                    path: []
                } as root_issue
                """
                root_result = session.run(root_query)
                root_record = root_result.single()
                if root_record:
                    results['issues'].insert(0, root_record['root_issue'])

                if sort or limit:
                    for key in results:
                        results[key] = sorted(
                            results[key],
                            key=lambda x: (-x['similarity'], x.get('distance', 0))
                        )
                        if limit:
                            results[key] = results[key][:limit]

                return results

            finally:
                if not reuse_projection:
                    session.run(
                        "CALL gds.graph.drop($graph_name, false)",
                        graph_name=graph_name,
                    )
                    if uniform_edge_weight:
                        self._uniform_similarity_projection_ready = False
                    else:
                        self._similarity_projection_ready = False

    @staticmethod
    def _compute_unsupervised_graph_rank_scores(
        candidate_items,
        alpha=0.85,
        iterations=24,
    ):
        filtered_candidates = [
            item for item in candidate_items
            if item.get("graph_node_id") is not None
        ]
        if not filtered_candidates:
            return {}

        root_node_id = None
        adjacency = {}
        all_nodes = set()
        for item in filtered_candidates:
            graph_node_id = item.get("graph_node_id")
            all_nodes.add(graph_node_id)
            path_nodes = item.get("graph_node_ids") or []
            if not path_nodes:
                continue
            if root_node_id is None:
                root_node_id = path_nodes[0]
            for i in range(len(path_nodes) - 1):
                src = path_nodes[i]
                dst = path_nodes[i + 1]
                all_nodes.add(src)
                all_nodes.add(dst)
                adjacency.setdefault(src, set()).add(dst)

        if root_node_id is None:
            return {item.get("graph_node_id"): 0.0 for item in filtered_candidates}

        root_node_id = int(root_node_id)
        all_nodes = {int(item) for item in all_nodes}
        scores = {node_id: 0.0 for node_id in all_nodes}
        scores[root_node_id] = 1.0

        for _ in range(iterations):
            next_scores = {node_id: 1.0 - alpha for node_id in all_nodes}
            for node_id, outs in list(adjacency.items()):
                if not outs:
                    continue
                current_score = scores.get(node_id, 0.0)
                if current_score <= 0:
                    continue
                share = alpha * current_score / len(outs)
                for out in outs:
                    next_scores[int(out)] = next_scores.get(int(out), 0.0) + share
            scores = next_scores

        if not scores:
            return {}
        max_score = max(scores.values())
        if max_score <= 0:
            return {node_id: 0.0 for node_id in scores.keys()}
        return {node_id: score / max_score for node_id, score in scores.items()}

    @staticmethod
    def _compute_similarity_score(item, decay_factor, vector_similarity_weight):
        if item.get("type") == "issue" and item.get("issue_id") == "root":
            return 2.0
        distance = item.get("distance", 0) or 0
        vec_sim = item.get("vector_similarity", 0) or 0
        text_sim = item.get("text_similarity", 0) or 0
        if item.get("type") == "issue":
            return vec_sim * (decay_factor ** distance)
        mixed = (
            vec_sim * vector_similarity_weight
            + text_sim * (1 - vector_similarity_weight)
        )
        return mixed * (decay_factor ** distance)

    def rank_similarity_components(
        self,
        components,
        decay_factor=None,
        vector_similarity_weight=None,
        limit=None,
        sort=False,
    ):
        decay_factor = DECAY_FACTOR if decay_factor is None else decay_factor
        vector_similarity_weight = (
            VECTOR_SIMILARITY_WEIGHT
            if vector_similarity_weight is None
            else vector_similarity_weight
        )
        limit = limit or 500

        results = {
            "methods": [],
            "classes": [],
            "issues": [],
        }

        for key in ("methods", "classes", "issues"):
            for item in components.get(key, []):
                scored = dict(item)
                scored["similarity"] = self._compute_similarity_score(
                    scored, decay_factor, vector_similarity_weight
                )
                results[key].append(scored)

        if sort or limit:
            for key in results:
                results[key] = sorted(
                    results[key],
                    key=lambda x: (-x.get("similarity", 0), x.get("distance", 0)),
                )
                if limit:
                    results[key] = results[key][:limit]
        return results

    def get_similarity_components_to_root(
        self,
        max_hops=2,
        candidate_limit=10000,
    ):
        with self.driver.session() as session:
            try:
                session.run("CALL gds.graph.drop('graph', false)")

                session.run("""
                CALL gds.graph.project(
                    'graph',
                    ['Issue', 'Method', 'Class', 'File', 'Directory', 'Commit'],
                    {
                        RELATED: {
                            type: 'RELATED',
                            orientation: 'NATURAL',
                            properties: {
                                weight: {
                                    property: 'weight',
                                    defaultValue: 1.0
                                }
                            }
                        }
                    }
                )
                """)

                method_query = """
                MATCH (root:Issue {id: 'root'})
                WHERE root.embedding IS NOT NULL
                WITH root, root.embedding as root_embedding,
                    root.title + ' ' + root.content as root_text

                MATCH (m)
                WHERE (m:Method OR m:Class OR (m:Issue AND m.id <> 'root'))
                AND m.embedding IS NOT NULL
                AND (NOT m:Method OR NOT m.name CONTAINS 'test' OR m.name CONTAINS 'pytest')

                CALL gds.shortestPath.dijkstra.stream('graph', {
                    sourceNode: root,
                    targetNode: m,
                    relationshipWeightProperty: 'weight'
                })
                YIELD nodeIds, totalCost

                WITH nodeIds, totalCost, root_embedding, root_text,
                    gds.util.asNode(nodeIds[-1]) as m
                WHERE (m:Method OR m:Class AND NOT EXISTS((m)-[:RELATED]->(:Method)) OR m:Issue)
                  AND totalCost <= $max_hops
                  AND (m:Issue AND m.id <> 'root' OR NOT m:Issue)

                WITH m, nodeIds, totalCost, root_embedding, root_text,
                    [i IN range(0, size(nodeIds)-2) |
                        [
                            (start)-[rel:RELATED]-(end)
                            WHERE id(start) = nodeIds[i] AND id(end) = nodeIds[i+1] |
                            {
                                start_node: CASE
                                    WHEN start:Commit THEN 'Commit#' + start.id
                                    WHEN start:Experience THEN start.name
                                    WHEN start:Documentation THEN start.name
                                    WHEN start:Issue THEN start.name
                                    ELSE start.name
                                END,
                                end_node: CASE
                                    WHEN end:Commit THEN 'Commit#' + end.id
                                    WHEN end:Experience THEN end.name
                                    WHEN end:Documentation THEN end.name
                                    WHEN end:Issue THEN end.name
                                    ELSE end.name
                                END,
                                start_labels: labels(start),
                                end_labels: labels(end),
                                start_type: CASE
                                    WHEN start:Method THEN 'method'
                                    WHEN start:Class THEN 'class'
                                    WHEN start:File THEN 'file'
                                    WHEN start:Issue THEN 'issue'
                                    WHEN start:Commit THEN 'commit'
                                    WHEN start:Experience THEN 'experience'
                                    WHEN start:Documentation THEN 'documentation'
                                    WHEN start:Directory THEN 'directory'
                                    ELSE 'unknown'
                                END,
                                end_type: CASE
                                    WHEN end:Method THEN 'method'
                                    WHEN end:Class THEN 'class'
                                    WHEN end:File THEN 'file'
                                    WHEN end:Issue THEN 'issue'
                                    WHEN end:Commit THEN 'commit'
                                    WHEN end:Experience THEN 'experience'
                                    WHEN end:Documentation THEN 'documentation'
                                    WHEN end:Directory THEN 'directory'
                                    ELSE 'unknown'
                                END,
                                type: type(rel),
                                description: CASE
                                    WHEN id(start) = id(startNode(rel)) THEN rel.description
                                    ELSE CASE
                                        WHEN rel.description = 'contains method' THEN 'contained in method'
                                        WHEN rel.description = 'contained in method' THEN 'contains method'
                                        WHEN rel.description = 'contains class' THEN 'contained in class'
                                        WHEN rel.description = 'contained in class' THEN 'contains class'
                                        WHEN rel.description = 'contains file' THEN 'contained in file'
                                        WHEN rel.description = 'contained in file' THEN 'contains file'
                                        WHEN rel.description = 'points to issue' THEN 'referenced by issue'
                                        WHEN rel.description = 'referenced by issue' THEN 'points to issue'
                                        WHEN rel.description = 'calls method' THEN 'called by method'
                                        WHEN rel.description = 'called by method' THEN 'calls method'
                                        ELSE rel.description
                                    END
                                END
                            }
                        ][0]
                    ] as path_details

                WITH m, nodeIds, path_details, totalCost as cost,
                    gds.similarity.cosine(root_embedding, m.embedding) as vector_similarity,
                    CASE
                        WHEN m:Issue THEN 0.0
                        ELSE apoc.text.levenshteinSimilarity(root_text, coalesce(m.source_code, ''))
                    END as text_similarity
                ORDER BY vector_similarity DESC
                LIMIT $candidate_limit

                RETURN collect({
                    type: CASE
                        WHEN m:Method THEN 'method'
                        WHEN m:Class THEN 'class'
                        ELSE 'issue'
                    END,
                    name: m.name,
                    signature: CASE WHEN m:Method THEN m.signature ELSE null END,
                    file_path: CASE WHEN m:Method OR m:Class THEN m.file_path ELSE null END,
                    documentation: CASE WHEN m:Method OR m:Class THEN m.doc_string ELSE null END,
                    source_code: CASE WHEN m:Method OR m:Class THEN m.source_code ELSE null END,
                    start_line: CASE WHEN m:Method OR m:Class THEN m.start_line ELSE null END,
                    end_line: CASE WHEN m:Method OR m:Class THEN m.end_line ELSE null END,
                    issue_id: CASE WHEN m:Issue THEN m.id ELSE null END,
                    title: CASE WHEN m:Issue THEN m.title ELSE null END,
                    content: CASE WHEN m:Issue THEN m.content ELSE null END,
                    vector_similarity: vector_similarity,
                    text_similarity: text_similarity,
                    distance: cost,
                    path: path_details
                }) as methods
                """

                method_result = session.run(
                    method_query,
                    max_hops=float(max_hops),
                    candidate_limit=int(candidate_limit),
                )
                method_record = method_result.single()
                method_similarities = method_record['methods'] if method_record else []

                results = {
                    'methods': list({
                        (sim['name'], sim.get('signature'), sim.get('file_path')): sim
                        for sim in method_similarities
                        if sim['type'] == 'method' and sim.get('vector_similarity') is not None
                    }.values()),
                    'classes': list({
                        (sim['name'], sim.get('file_path')): sim
                        for sim in method_similarities
                        if sim['type'] == 'class' and sim.get('vector_similarity') is not None
                    }.values()),
                    'issues': list({
                        sim['issue_id']: sim
                        for sim in method_similarities
                        if sim['type'] == 'issue' and sim.get('vector_similarity') is not None
                    }.values())
                }

                root_query = """
                MATCH (root:Issue {id: 'root'})
                RETURN {
                    type: 'issue',
                    name: root.name,
                    issue_id: root.id,
                    title: root.title,
                    content: root.content,
                    vector_similarity: 1.0,
                    text_similarity: 1.0,
                    similarity: 2.0,
                    distance: 0,
                    path: []
                } as root_issue
                """
                root_result = session.run(root_query)
                root_record = root_result.single()
                if root_record:
                    results['issues'].insert(0, root_record['root_issue'])
                return results

            finally:
                session.run("CALL gds.graph.drop('graph', false)")

    def _create_indexes(self):
        """Create database indexes to improve query performance"""
        with self.driver.session() as session:
            # Method node index
            session.run("""
                CREATE INDEX method_composite IF NOT EXISTS
                FOR (m:Method)
                ON (m.name, m.signature, m.file_path)
            """)

            # Issue node index
            session.run("""
                CREATE INDEX issue_id IF NOT EXISTS
                FOR (i:Issue)
                ON (i.id)
            """)

            # File node index
            session.run("""
                CREATE INDEX file_path IF NOT EXISTS
                FOR (f:File)
                ON (f.path)
            """)

            # Class node index
            session.run("""
                CREATE INDEX class_composite IF NOT EXISTS
                FOR (c:Class)
                ON (c.name, c.file_path)
            """)

            # Commit node index
            session.run("""
                CREATE INDEX commit_id IF NOT EXISTS
                FOR (c:Commit)
                ON (c.id)
            """)

            session.run("""
                CREATE INDEX experience_id IF NOT EXISTS
                FOR (e:Experience)
                ON (e.id)
            """)

            session.run("""
                CREATE INDEX documentation_id IF NOT EXISTS
                FOR (d:Documentation)
                ON (d.id)
            """)

            # Directory node index
            session.run("""
                CREATE INDEX directory_path IF NOT EXISTS
                FOR (d:Directory)
                ON (d.path)
            """)

            print("Successfully created all indexes")

    def link_class_to_file(self, class_name, file_path, weight=1):
        """
        Establish relationship between class and file

        Args:
            class_name (str): Class name
            file_path (str): File path
        """
        with self.driver.session() as session:
            query = """
            MATCH (c:Class {name: $class_name, file_path: $file_path})
            MATCH (f:File {path: $file_path})
            MERGE (c)-[:RELATED {description: 'contained in file', weight: $weight}]->(f)
            MERGE (f)-[:RELATED {description: 'contains class', weight: $weight}]->(c)
            """
            session.run(query,
                class_name=class_name,
                file_path=file_path,
                weight=weight
            )

    def link_method_to_file(self, method_name, method_signature, file_path, weight=1):
        """
        Establish relationship between method and file

        Args:
            method_name (str): Method name
            method_signature (str): Method signature
            file_path (str): File path
        """
        with self.driver.session() as session:
            query = """
            MATCH (m:Method {name: $method_name, signature: $method_signature, file_path: $file_path})
            MATCH (f:File {path: $file_path})
            MERGE (m)-[:RELATED {description: 'contained in file', weight: $weight}]->(f)
            MERGE (f)-[:RELATED {description: 'contains method', weight: $weight}]->(m)
            """
            session.run(query,
                method_name=method_name,
                method_signature=method_signature,
                file_path=file_path,
                weight=weight
            )
